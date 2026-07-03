"""Fix strategy: select prompt template based on violation type and call LLM."""
from __future__ import annotations

import json
import logging
import re
import tempfile
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path

from openai import OpenAI
from agent.budget_policy import BudgetPolicy, evaluate_budget
from agent.config import AgentConfig
from agent.llm_provider import LLMProvider, complete_response
from agent.metrics import Metrics
from agent.mumei_client import MumeiClient
from agent.pattern_library import PatternLibrary
from agent.prompts import (
    effect_mismatch,
    effect_propagation,
    precondition,
    division_by_zero,
    linearity,
    invariant,
    postcondition,
    temporal_effect,
)
from agent.spec_code_mapper import SpecCodeMapper
from agent.strategies.retry_history import RetryHistory
from agent.strategies.rule_based_fix import try_rule_based_fix
from agent.prompts.report_formatter import format_actionable_fix_hint

from agent.strategies.fix_strategy_helpers import (
    CyclicDependencyWarning,
    _IMPORT_RE,
    _SUPPORTED_LOSS_SCHEMA_VERSION,
    _aggregate_heal_results,
    _candidate_import_paths,
    _classify_structured_error,
    _format_loss_vector_guidance,
    _loss_counterexample,
    _loss_schema_supported,
    _loss_schema_version,
    _loss_vector,
    _nested_dict,
    _parse_import_targets,
    _reconstruction_loss_payload,
    _record_pattern,
    _repair_strategy_for_error,
    _structured_feedback,
    _update_spec_code_mapping,
    build_dependency_graph,
    interpret_structured_feedback,
    json_dumps_loss_vector,
    response_token_count,
    topological_sort_files,
)

@dataclass
class SelfCorrectionResult:
    success: bool
    iterations: int
    stop_reason: str | None = None
    loss_vector: dict | None = None
    history: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# Mapping from failure_type to prompt module
_FAILURE_TYPE_MAP = {
    "division_by_zero": division_by_zero,
    "linearity_violated": linearity,
    "invariant_violated": invariant,
    "postcondition_violated": postcondition,
    "temporal_effect_violated": temporal_effect,
}

class SelfCorrectionLoop:
    """P9-F generate → verify → loss-vector repair loop."""

    def __init__(
        self,
        max_iterations: int = 10,
        convergence_threshold: float = 0.7,
    ) -> None:
        self.max_iterations = max(1, min(max_iterations, 10))
        self.convergence_threshold = convergence_threshold

    def run(self, code_file: Path, mumei_client, llm_client) -> SelfCorrectionResult:
        path = Path(code_file)
        history: list[dict[str, object]] = []
        last_loss_vector: dict | None = None

        for iteration in range(1, self.max_iterations + 1):
            verify_result = mumei_client.verify(str(path))
            all_verified = self._all_verified(verify_result)
            loss_vector = self._loss_vector(verify_result)
            last_loss_vector = loss_vector
            history.append(
                {
                    "iteration": iteration,
                    "all_verified": all_verified,
                    "has_loss_vector": loss_vector is not None,
                }
            )
            if all_verified:
                return SelfCorrectionResult(
                    success=True,
                    iterations=iteration,
                    stop_reason="all_verified",
                    loss_vector=loss_vector,
                    history=history,
                )
            if loss_vector is None:
                return SelfCorrectionResult(
                    success=False,
                    iterations=iteration,
                    stop_reason="loss_vector_missing",
                    history=history,
                )
            fix = llm_client.fix_with_loss_vector(path, loss_vector)
            if not fix:
                return SelfCorrectionResult(
                    success=False,
                    iterations=iteration,
                    stop_reason="no_fix_produced",
                    loss_vector=loss_vector,
                    history=history,
                )
            path.write_text(fix, encoding="utf-8")

        return SelfCorrectionResult(
            success=False,
            iterations=self.max_iterations,
            stop_reason="max_iterations",
            loss_vector=last_loss_vector,
            history=history,
        )

    @staticmethod
    def _all_verified(verify_result: dict) -> bool:
        explicit = verify_result.get("all_verified")
        if isinstance(explicit, bool):
            return explicit
        success = verify_result.get("success")
        if isinstance(success, bool) and success:
            return True
        status = verify_result.get("status")
        if isinstance(status, str) and status in {
            "verification_passed",
            "passed",
            "success",
        }:
            return True
        report = verify_result.get("report")
        if isinstance(report, dict):
            report_status = report.get("status")
            if isinstance(report_status, str) and report_status in {
                "verification_passed",
                "passed",
                "success",
            }:
                return True
            feedback = report.get("structured_feedback")
            if isinstance(feedback, dict):
                feedback_status = feedback.get("status")
                return feedback_status == "verification_passed"
        return False

    @staticmethod
    def _loss_vector(verify_result: dict) -> dict | None:
        direct = verify_result.get("loss_vector")
        if isinstance(direct, dict):
            return direct
        report = verify_result.get("report")
        if isinstance(report, dict):
            report_loss = report.get("loss_vector")
            if isinstance(report_loss, dict):
                return report_loss
            feedback = report.get("structured_feedback")
            if isinstance(feedback, dict) and feedback.get("status") == "verification_failed":
                return feedback
        return None


class OpenAILossVectorFixClient:
    """Adapter exposing ``fix_with_loss_vector`` over the existing get_fix path."""

    def __init__(
        self,
        client: OpenAI | LLMProvider,
        model: str,
        mumei_client: MumeiClient | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.mumei_client = mumei_client

    def fix_with_loss_vector(self, code_file: Path, loss_vector: dict) -> str:
        source_code = code_file.read_text(encoding="utf-8")
        error_log = f"loss_vector:\n{json_dumps_loss_vector(loss_vector)}"
        report_data = dict(loss_vector)
        report_data.setdefault("loss_vector", loss_vector)
        return get_fix(
            self.client,
            self.model,
            source_code,
            error_log,
            report_data,
            mumei_client=self.mumei_client,
            source_path=str(code_file),
        )


class ConfiguredLossVectorFixClient:
    """Lazy OpenAI adapter for self-correction loops."""

    def __init__(
        self,
        config: AgentConfig,
        mumei_client: MumeiClient | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.config = config
        self.mumei_client = mumei_client
        self.llm_provider = llm_provider
        self._delegate: OpenAILossVectorFixClient | None = None

    def fix_with_loss_vector(self, code_file: Path, loss_vector: dict) -> str:
        if self._delegate is None:
            self._delegate = OpenAILossVectorFixClient(
                self.llm_provider or self.config.create_client(),
                self.config.model,
                self.mumei_client,
            )
        return self._delegate.fix_with_loss_vector(code_file, loss_vector)





def _build_prompt_for_report(source_code: str, error_log: str, report_data: dict) -> str:
    """Select the appropriate prompt template and build the prompt string."""
    violation_type = report_data.get("violation_type", "")
    failure_type = report_data.get("failure_type", "") or _classify_structured_error(report_data)

    if violation_type == "effect_mismatch":
        return effect_mismatch.build_prompt(source_code, error_log, report_data)
    elif violation_type == "effect_propagation":
        return effect_propagation.build_prompt(source_code, error_log, report_data)
    elif failure_type in _FAILURE_TYPE_MAP:
        return _FAILURE_TYPE_MAP[failure_type].build_prompt(source_code, error_log, report_data)
    else:
        return precondition.build_prompt(source_code, error_log, report_data)


def get_fix(
    client: OpenAI | LLMProvider,
    model: str,
    source_code: str,
    error_log: str,
    report_data: dict,
    *,
    strategy: str = "single",
    mumei_client: MumeiClient | None = None,
    source_path: str | None = None,
    retry_history: RetryHistory | None = None,
    metrics: Metrics | None = None,
    pattern_library: PatternLibrary | None = None,
    enable_latent_debug: bool | None = None,
    spec: dict | None = None,
    enable_spec_code_mapping: bool | None = None,
    budget_policy: BudgetPolicy | None = None,
    action_class: str | None = None,
) -> str:
    """Generate a fix using the appropriate prompt template.

    Args:
        client: LLMProvider or OpenAI-compatible client.
        model: Model name.
        source_code: Current source code.
        error_log: Verification error output.
        report_data: Structured verification report.
        strategy: "single" (default) for one-shot, "multi-stage" for 3-stage pipeline.
        mumei_client: MumeiClient instance (required for multi-stage).
        source_path: Path to source file (required for multi-stage).
        retry_history: Optional retry history for context across attempts.
        metrics: Optional Metrics instance for tracking rule-based vs LLM fixes.
        pattern_library: Optional PatternLibrary for few-shot examples.
        enable_latent_debug: When true, try latent-space debugging first.
        spec: Optional original specification used to update mapping metadata.
        enable_spec_code_mapping: When true, update spec-code mapping after fixes.
        budget_policy: Optional retry budget policy.
        action_class: Optional action class selected by the caller.
    """
    if enable_latent_debug is None:
        try:
            from agent.config import AgentConfig
            enable_latent_debug = AgentConfig().enable_latent_debug
        except Exception:
            enable_latent_debug = False

    if enable_spec_code_mapping is None:
        try:
            from agent.config import AgentConfig
            enable_spec_code_mapping = AgentConfig().enable_spec_code_mapping
        except Exception:
            enable_spec_code_mapping = True

    interpretation = interpret_structured_feedback(report_data)
    if not interpretation["schema_supported"]:
        report_data["manual_review_required"] = {
            "status": "manual_review_required",
            "reason": "unsupported_loss_schema",
            "schema_version": interpretation["schema_version"],
        }
        report_data["loss_vector_interpretation"] = interpretation
        return ""
    if not report_data.get("failure_type") and interpretation["error_type"] != "unknown":
        report_data["failure_type"] = interpretation["error_type"]
    report_data["loss_vector_interpretation"] = interpretation
    if action_class is None and interpretation["repair_strategy"] != "generic_verifier_repair":
        action_class = str(interpretation["repair_strategy"])

    vt = report_data.get("violation_type") or report_data.get("failure_type", "unknown")
    if budget_policy is not None and retry_history is not None:
        decision = evaluate_budget(
            budget_policy,
            retry_history,
            report_data,
            proposed_action_class=action_class,
        )
        if not decision.allowed:
            report_data["manual_review_required"] = decision.summary
            return ""
        action_class = decision.action_class

    # Phase 0: optional latent-space debug.  Any failure falls through to
    # the existing deterministic rule-based and LLM repair pipeline.
    if enable_latent_debug:
        try:
            from agent.latent_decoder import LatentDecoder
            from agent.latent_encoder import LatentEncoder
            from agent.strategies.latent_debug_strategy import LatentDebugStrategy

            if metrics is not None:
                metrics.record_latent_debug_attempt(vt)
            latent_fix = LatentDebugStrategy().get_fix_with_latent_debug(
                source_code,
                report_data,
                LatentEncoder(),
                LatentDecoder(),
            )
            if latent_fix:
                if mumei_client is not None:
                    tmp_path: str | None = None
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="w",
                            suffix=".mm",
                            delete=False,
                            encoding="utf-8",
                        ) as tmp:
                            tmp_path = tmp.name
                            tmp.write(latent_fix)
                        validation = mumei_client.verify(tmp_path)
                        if validation["success"]:
                            if metrics is not None:
                                metrics.record_latent_debug_success(vt)
                            _record_pattern(
                                pattern_library, vt,
                                report_data.get("failure_type", ""),
                                source_code, latent_fix, report_data,
                                fix_method="latent_debug",
                            )
                            _update_spec_code_mapping(
                                report_data,
                                spec,
                                latent_fix,
                                enable_spec_code_mapping,
                            )
                            return latent_fix
                    except Exception:
                        logging.getLogger(__name__).warning(
                            "Latent debug validation failed; falling through",
                            exc_info=True,
                        )
                    finally:
                        try:
                            if tmp_path:
                                Path(tmp_path).unlink(missing_ok=True)
                        except Exception:
                            pass
                else:
                    if metrics is not None:
                        metrics.record_latent_debug_success(vt)
                    _record_pattern(
                        pattern_library, vt,
                        report_data.get("failure_type", ""),
                        source_code, latent_fix, report_data,
                        fix_method="latent_debug",
                    )
                    _update_spec_code_mapping(
                        report_data,
                        spec,
                        latent_fix,
                        enable_spec_code_mapping,
                    )
                    return latent_fix
        except Exception:
            logging.getLogger(__name__).warning(
                "Latent debug initialization failed; falling through",
                exc_info=True,
            )

    # Phase 1: Try rule-based fix (no LLM, deterministic)
    rule_fix = try_rule_based_fix(source_code, report_data)
    if rule_fix is not None:
        if metrics is not None:
            metrics.record_rule_based_attempt(vt)
        if mumei_client is not None:
            tmp_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".mm", delete=False, encoding="utf-8",
                ) as tmp:
                    tmp_path = tmp.name
                    tmp.write(rule_fix)
                validation = mumei_client.verify(tmp_path)
                if validation["success"]:
                    if metrics is not None:
                        metrics.record_rule_based_success(vt)
                    _record_pattern(
                        pattern_library, vt,
                        report_data.get("failure_type", ""),
                        source_code, rule_fix, report_data,
                        fix_method="rule_based",
                    )
                    _update_spec_code_mapping(
                        report_data,
                        spec,
                        rule_fix,
                        enable_spec_code_mapping,
                    )
                    return rule_fix
            except Exception:
                # Infrastructure failure (binary not found, OS error, etc.)
                # — fall through to LLM-based Phase 2.
                logging.getLogger(__name__).warning(
                    "Rule-based fix validation failed due to infrastructure error; "
                    "falling through to LLM.",
                    exc_info=True,
                )
            finally:
                try:
                    if tmp_path:
                        Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass
            # Rule-based fix failed validation — fall through to LLM.
            # record_rule_based_attempt only incremented rule_based_attempts
            # (not total_attempts), so the LLM path's own metrics tracking
            # remains unaffected.
        else:
            # No mumei_client to validate — return the rule-based fix as-is
            if metrics is not None:
                metrics.record_rule_based_success(vt)
            _record_pattern(
                pattern_library, vt,
                report_data.get("failure_type", ""),
                source_code, rule_fix, report_data,
                fix_method="rule_based",
            )
            _update_spec_code_mapping(
                report_data,
                spec,
                rule_fix,
                enable_spec_code_mapping,
            )
            return rule_fix

    # Phase 1.5: Try pattern-based fix
    if pattern_library is not None and mumei_client is not None:
        # Only record an attempt when there are actual candidates for
        # this violation type.  Without this guard, every call through
        # get_fix() with an empty pattern library would inflate
        # pattern_attempts with phantom attempts that never had a
        # chance of succeeding.
        has_candidates = bool(pattern_library.lookup(vt, max_results=1))
        if has_candidates:
            if metrics is not None:
                metrics.record_pattern_attempt(vt)
            pattern_fix = pattern_library.try_pattern_fix(vt, source_code, report_data, mumei_client)
            if pattern_fix is not None:
                if metrics is not None:
                    metrics.record_pattern_success(vt)
                _update_spec_code_mapping(
                    report_data,
                    spec,
                    pattern_fix,
                    enable_spec_code_mapping,
                )
                return pattern_fix

    # Phase 2: LLM-based fix (existing logic)
    if strategy == "multi-stage":
        if mumei_client is not None and source_path is not None:
            from agent.strategies.multi_stage_strategy import get_fix_multi_stage
            fixed_code = get_fix_multi_stage(
                client, model, source_code, error_log, report_data,
                mumei_client, source_path,
                retry_history=retry_history,
                metrics=metrics,
                pattern_library=pattern_library,
                action_class=action_class or "llm_fix",
            )
            _update_spec_code_mapping(
                report_data,
                spec,
                fixed_code,
                enable_spec_code_mapping,
            )
            return fixed_code
        logging.getLogger(__name__).warning(
            "multi-stage strategy requested but mumei_client or source_path is None; "
            "falling back to single-shot strategy."
        )

    prompt = _build_prompt_for_report(source_code, error_log, report_data)

    # Enrich with actionable fix hint
    hint = format_actionable_fix_hint(report_data)
    if hint:
        prompt += f"\n\n# Actionable fix instructions:\n{hint}"

    loss_guidance = _format_loss_vector_guidance(report_data)
    if loss_guidance:
        prompt += f"\n\n# Structured feedback interpretation:\n{loss_guidance}"

    if action_class:
        prompt += (
            "\n\n# Retry budget action class\n"
            f"Use action class `{action_class}`. If this class is exhausted, switch "
            "to a materially different repair strategy rather than weakening the specification."
        )

    # Enrich with few-shot examples from pattern library
    if pattern_library is not None:
        few_shot = pattern_library.format_few_shot(vt)
        if few_shot:
            prompt += f"\n\n{few_shot}"

    response = complete_response(
        client,
        [
            {
                "role": "system",
                "content": (
                    "You are a helpful programming assistant specializing "
                    "in the Mumei language with its effect system and Z3 formal verification."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        model,
    )
    llm_tokens_used = response_token_count(response)
    if metrics is not None:
        metrics.record_tokens(llm_tokens_used)
    report_data["llm_tokens_used"] = llm_tokens_used

    # Extract code block (handles various LLM fence labels)
    content = response.choices[0].message.content or ""
    code_match = re.search(
        r'```\w*\s*\n(.*?)```',
        content,
        re.DOTALL,
    )
    if code_match:
        fixed_code = code_match.group(1).strip()
    else:
        fixed_code = content.strip()
    _update_spec_code_mapping(
        report_data,
        spec,
        fixed_code,
        enable_spec_code_mapping,
    )
    return fixed_code
