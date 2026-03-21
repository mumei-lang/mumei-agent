"""Fix strategy: select prompt template based on violation type and call LLM."""
from __future__ import annotations

import re
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
from agent.strategies.retry_history import RetryHistory

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
    """
    if strategy == "multi-stage":
        if mumei_client is not None and source_path is not None:
            from agent.strategies.multi_stage_strategy import get_fix_multi_stage
            return get_fix_multi_stage(
                client, model, source_code, error_log, report_data,
                mumei_client, source_path,
                retry_history=retry_history,
            )
        import logging
        logging.getLogger(__name__).warning(
            "multi-stage strategy requested but mumei_client or source_path is None; "
            "falling back to single-shot strategy."
        )

    prompt = _build_prompt_for_report(source_code, error_log, report_data)

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
