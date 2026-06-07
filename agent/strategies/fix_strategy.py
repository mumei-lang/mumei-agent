"""Fix strategy: select prompt template based on violation type and call LLM."""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from openai import OpenAI
from agent.budget_policy import BudgetPolicy, evaluate_budget
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

# Mapping from failure_type to prompt module
_FAILURE_TYPE_MAP = {
    "division_by_zero": division_by_zero,
    "linearity_violated": linearity,
    "invariant_violated": invariant,
    "postcondition_violated": postcondition,
    "temporal_effect_violated": temporal_effect,
}

_SUPPORTED_LOSS_SCHEMA_VERSION = "p9-de/v1"


def _nested_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    return None


def _structured_feedback(report_data: dict) -> dict[str, object]:
    return _nested_dict(report_data.get("structured_feedback")) or {}


def _reconstruction_loss_payload(report_data: dict) -> dict[str, object]:
    structured_loss = _nested_dict(_structured_feedback(report_data).get("reconstruction_loss"))
    if structured_loss is not None:
        return structured_loss
    semantic_feedback = _nested_dict(report_data.get("semantic_feedback")) or {}
    semantic_loss = _nested_dict(semantic_feedback.get("reconstruction_loss"))
    if semantic_loss is not None:
        return semantic_loss
    return _nested_dict(report_data.get("reconstruction_loss")) or {}


def _loss_vector(report_data: dict) -> list[float]:
    payload = _reconstruction_loss_payload(report_data)
    raw_vector = payload.get("loss_vector")
    if not isinstance(raw_vector, list):
        return []
    vector: list[float] = []
    for component in raw_vector:
        if isinstance(component, int | float):
            vector.append(float(component))
        elif isinstance(component, dict):
            magnitude = component.get("magnitude")
            if isinstance(magnitude, int | float):
                vector.append(float(magnitude))
    return vector


def _loss_counterexample(report_data: dict) -> dict[str, object]:
    payload = _reconstruction_loss_payload(report_data)
    return _nested_dict(payload.get("counter_example")) or _nested_dict(
        report_data.get("counterexample")
    ) or {}


def _loss_schema_version(report_data: dict) -> str:
    payload = _reconstruction_loss_payload(report_data)
    schema_version = payload.get("schema_version")
    return schema_version if isinstance(schema_version, str) else ""


def _loss_schema_supported(report_data: dict) -> bool:
    schema_version = _loss_schema_version(report_data)
    return schema_version in {"", _SUPPORTED_LOSS_SCHEMA_VERSION}


def _classify_structured_error(report_data: dict) -> str:
    feedback = _structured_feedback(report_data)
    error_type = feedback.get("error_type")
    if isinstance(error_type, str) and error_type:
        return error_type
    payload = _reconstruction_loss_payload(report_data)
    violated_property = payload.get("violated_property")
    property_text = violated_property.lower() if isinstance(violated_property, str) else ""
    counterexample = _loss_counterexample(report_data)
    divisor_is_zero = counterexample.get("divisor") == 0
    slash_divisor_is_zero = counterexample.get("b") == 0 and "/" in property_text
    if divisor_is_zero or slash_divisor_is_zero:
        return "division_by_zero"
    if "requires" in property_text:
        return "precondition_violated"
    if "ensures" in property_text or "result" in property_text:
        return "postcondition_violated"
    return ""


def _repair_strategy_for_error(error_type: str, vector: list[float]) -> str:
    if error_type == "division_by_zero":
        return "strengthen_nonzero_precondition"
    if error_type == "postcondition_violated":
        return "repair_body_to_reduce_l_recon"
    if error_type == "precondition_violated":
        return "repair_callsite_or_requires"
    if error_type == "invariant_violated":
        return "repair_invariant_constraint"
    if any(abs(component) > 0.0 for component in vector):
        return "target_largest_loss_component"
    return "generic_verifier_repair"


def interpret_structured_feedback(report_data: dict) -> dict[str, object]:
    vector = _loss_vector(report_data)
    error_type = (
        report_data.get("failure_type")
        if isinstance(report_data.get("failure_type"), str)
        else ""
    ) or _classify_structured_error(report_data)
    magnitude = sum(abs(component) for component in vector)
    return {
        "error_type": error_type or "unknown",
        "loss_magnitude": magnitude,
        "repair_strategy": _repair_strategy_for_error(error_type, vector),
        "counterexample": _loss_counterexample(report_data),
        "schema_version": _loss_schema_version(report_data) or "legacy",
        "schema_supported": _loss_schema_supported(report_data),
    }


def _format_loss_vector_guidance(report_data: dict) -> str:
    payload = _reconstruction_loss_payload(report_data)
    if not payload:
        return ""
    vector = _loss_vector(report_data)
    interpretation = interpret_structured_feedback(report_data)
    counterexample = _loss_counterexample(report_data)
    violated_property = payload.get("violated_property", "")
    lines = [
        "Structured feedback loss vector:",
        f"- violated_property: {violated_property}",
        f"- loss_vector: {vector}",
        f"- total L_recon: {interpretation['loss_magnitude']}",
        f"- selected repair strategy: {interpretation['repair_strategy']}",
    ]
    if counterexample:
        pairs = ", ".join(f"{key}={value}" for key, value in counterexample.items())
        lines.append(f"- counterexample: {pairs}")
    lines.append("Prioritize edits that reduce non-zero L_recon components without weakening the contract.")
    return "\n".join(lines)


def response_token_count(response: object) -> int:
    try:
        usage = response.usage
    except AttributeError:
        return 0
    if usage is None:
        return 0
    if isinstance(usage, dict):
        total_tokens = usage.get("total_tokens")
    else:
        try:
            total_tokens = usage.total_tokens
        except AttributeError:
            return 0
    try:
        return int(total_tokens or 0)
    except (TypeError, ValueError):
        return 0


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
    client: OpenAI,
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
        client: OpenAI-compatible client.
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

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful programming assistant specializing "
                    "in the Mumei language with its effect system and Z3 formal verification."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    llm_tokens_used = response_token_count(response)
    if metrics is not None:
        metrics.record_tokens(llm_tokens_used)
    report_data["llm_tokens_used"] = llm_tokens_used

    content = response.choices[0].message.content or ""
    # Extract code block (handles various LLM fence labels)
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


def _update_spec_code_mapping(
    report_data: dict,
    spec: dict | None,
    fixed_code: str,
    enabled: bool | None,
) -> None:
    """Update structured report mapping metadata after a fix."""
    if not enabled or not spec or not fixed_code:
        return
    try:
        mapper = SpecCodeMapper()
        result = mapper.build_mapping(spec, fixed_code, report_data)
        report_data["spec_code_mapping"] = mapper.to_json(result.mappings)
    except Exception:
        logging.getLogger(__name__).warning(
            "Failed to update spec-code mapping after fix",
            exc_info=True,
        )


def _record_pattern(
    pattern_library: PatternLibrary | None,
    violation_type: str,
    failure_type: str,
    source_before: str,
    source_after: str,
    report: dict,
    *,
    fix_method: str = "llm",
) -> None:
    """Record a successful fix pattern if a pattern library is provided."""
    if pattern_library is None:
        return
    try:
        pattern_library.record(
            violation_type=violation_type,
            failure_type=failure_type,
            source_before=source_before,
            source_after=source_after,
            report=report,
            fix_method=fix_method,
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "Failed to record pattern to library",
            exc_info=True,
        )
