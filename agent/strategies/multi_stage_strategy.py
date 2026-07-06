"""Multi-stage fix strategy: diagnose -> fix -> validate."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from openai import OpenAI

from agent import telemetry
from agent.mumei_client import MumeiClient
from agent.pattern_library import PatternLibrary
from agent.prompts.report_formatter import truncate_prompt_section
from agent.strategies.fix_strategy import _build_prompt_for_report, response_token_count
from agent.strategies.multi_stage_strategy_helpers import (
    _APPROACH_SWITCH_INSTRUCTION,
    _DIAGNOSE_SYSTEM,
    _DIAGNOSE_USER_TEMPLATE,
    _build_retry_context,
    _default_prompt_report_truncate_chars,
    _diagnose,
    _extract_code,
    _parse_diagnosis,
)
from agent.strategies.retry_history import RetryAttempt, RetryHistory

if TYPE_CHECKING:
    from agent.metrics import Metrics

_logger = logging.getLogger(__name__)

_FIX_SYSTEM = (
    "You are a helpful programming assistant specializing "
    "in the Mumei language with its effect system and Z3 formal verification."
)

_FIX_USER_TEMPLATE = """\
{base_prompt}

# Diagnosis:
- Root cause: {root_cause}
- Fix approach: {fix_approach}
- Target section: {target_section}
{retry_context}
Apply the fix approach above. Output only the fixed code in ```mumei ... ``` format.
"""

_MAX_INTERNAL_RETRIES = 2


def get_fix_multi_stage(
    client: OpenAI,
    model: str,
    source_code: str,
    error_log: str,
    report_data: dict,
    mumei_client: MumeiClient,
    source_path: str,
    retry_history: RetryHistory | None = None,
    metrics: Metrics | None = None,  # noqa: ARG001 — reserved for future use
    pattern_library: PatternLibrary | None = None,
    action_class: str = "llm_fix",
    prompt_report_truncate_chars: int | None = None,
) -> str:
    """Generate a fix using a multi-stage LLM pipeline.

    Stage 1 (Diagnose): Analyze the report and produce a structured diagnosis.
    Stage 2 (Fix): Generate fixed code using the diagnosis + prompt template.
    Stage 3 (Validate): Verify the fix with mumei; retry Stage 1+2+3 up to
        ``_MAX_INTERNAL_RETRIES`` times on failure.

    Args:
        metrics: Accepted for interface consistency with :func:`get_fix`
            but not yet used inside the multi-stage loop.  Future work
            should wire this into the internal retry accounting.
        pattern_library: Optional PatternLibrary for few-shot examples and
            recording successful fixes.

    Returns the fixed source code (best effort).
    """
    if retry_history is None:
        retry_history = RetryHistory()
    if prompt_report_truncate_chars is None:
        prompt_report_truncate_chars = _default_prompt_report_truncate_chars()

    best_fix = ""
    for retry in range(_MAX_INTERNAL_RETRIES + 1):
        # --- Stage 1: Diagnose (re-run each iteration) ---
        approach_switch = retry_history.is_same_error_repeating()
        diagnosis, diagnose_tokens = _diagnose(
            client,
            model,
            source_code,
            error_log,
            report_data,
            approach_switch=approach_switch,
        )

        root_cause = diagnosis.get("root_cause", "unknown")
        fix_approach = diagnosis.get("fix_approach", "apply general fix")
        target_section = diagnosis.get("target_section", "requires")

        # --- Stage 2: Fix ---
        base_prompt = _build_prompt_for_report(source_code, error_log, report_data)

        # Enrich with few-shot examples from pattern library
        vt = report_data.get("violation_type") or report_data.get("failure_type", "unknown")
        if pattern_library is not None:
            few_shot = pattern_library.format_few_shot(vt)
            if few_shot:
                base_prompt += f"\n\n{few_shot}"

        retry_context = _build_retry_context(retry_history)

        fix_prompt = _FIX_USER_TEMPLATE.format(
            base_prompt=base_prompt,
            root_cause=root_cause,
            fix_approach=fix_approach,
            target_section=target_section,
            retry_context=retry_context,
        )

        tracer = telemetry.get_tracer(__name__)
        with tracer.start_as_current_span("llm.multi_stage_fix") as span:
            span.set_attribute("gen_ai.system", "openai-compatible")
            span.set_attribute("gen_ai.request.model", model)
            fix_response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _FIX_SYSTEM},
                    {"role": "user", "content": fix_prompt},
                ],
            )
        fix_tokens = response_token_count(fix_response, model)
        total_tokens = diagnose_tokens + fix_tokens
        report_data["llm_tokens_used"] = total_tokens
        if metrics is not None:
            metrics.record_tokens(total_tokens)

        fixed_code = _extract_code(fix_response.choices[0].message.content or "")
        if not fixed_code:
            continue

        best_fix = fixed_code

        # --- Stage 3: Validate ---
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mm", delete=False, encoding="utf-8"
            ) as tmp:
                tmp_path = tmp.name
                tmp.write(fixed_code)

            validation = mumei_client.verify(tmp_path)
            if validation["success"]:
                # Record successful fix in pattern library
                if pattern_library is not None:
                    try:
                        pattern_library.record(
                            violation_type=vt,
                            failure_type=report_data.get("failure_type", ""),
                            source_before=source_code,
                            source_after=fixed_code,
                            report=report_data,
                            fix_method="llm",
                        )
                    except Exception:
                        _logger.warning(
                            "Failed to record pattern to library",
                            exc_info=True,
                        )
                return fixed_code  # Verified successfully!

            # Record the failed attempt
            new_error_log = validation["stdout"] + validation["stderr"]
            truncated_error_log = truncate_prompt_section(
                new_error_log,
                prompt_report_truncate_chars,
            )
            new_report = validation["report"] or report_data

            retry_history.add(
                RetryAttempt(
                    attempt_number=len(retry_history.attempts) + 1,
                    source_code=fixed_code,
                    error_log=truncated_error_log,
                    report_data=new_report,
                    diagnosis=diagnosis,
                    action_class=action_class,
                    tokens_used=total_tokens,
                )
            )

            # Update context for next iteration
            source_code = fixed_code
            error_log = truncated_error_log
            report_data = new_report
        except Exception:
            _logger.warning(
                "Validation infrastructure failure on retry %d; "
                "skipping history record",
                retry,
                exc_info=True,
            )
        finally:
            try:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    return best_fix
