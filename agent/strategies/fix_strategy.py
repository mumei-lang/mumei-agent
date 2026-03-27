"""Fix strategy: select prompt template based on violation type and call LLM."""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from openai import OpenAI
from agent.mumei_client import MumeiClient
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
from agent.metrics import Metrics
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


def _build_prompt_for_report(source_code: str, error_log: str, report_data: dict) -> str:
    """Select the appropriate prompt template and build the prompt string."""
    violation_type = report_data.get("violation_type", "")
    failure_type = report_data.get("failure_type", "")

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
    """
    # Phase 1: Try rule-based fix (no LLM, deterministic)
    vt = report_data.get("violation_type") or report_data.get("failure_type", "unknown")
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
            return rule_fix

    # Phase 2: LLM-based fix (existing logic)
    if strategy == "multi-stage":
        if mumei_client is not None and source_path is not None:
            from agent.strategies.multi_stage_strategy import get_fix_multi_stage
            return get_fix_multi_stage(
                client, model, source_code, error_log, report_data,
                mumei_client, source_path,
                retry_history=retry_history,
                metrics=metrics,
            )
        logging.getLogger(__name__).warning(
            "multi-stage strategy requested but mumei_client or source_path is None; "
            "falling back to single-shot strategy."
        )

    prompt = _build_prompt_for_report(source_code, error_log, report_data)

    # Enrich with actionable fix hint
    hint = format_actionable_fix_hint(report_data)
    if hint:
        prompt += f"\n\n# Actionable fix instructions:\n{hint}"

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

    content = response.choices[0].message.content or ""
    # Extract code block (handles various LLM fence labels)
    code_match = re.search(
        r'```\w*\s*\n(.*?)```',
        content,
        re.DOTALL,
    )
    if code_match:
        return code_match.group(1).strip()
    return content.strip()
