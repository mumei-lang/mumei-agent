"""Multi-stage fix strategy: diagnose -> fix -> validate."""
from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from openai import OpenAI

from agent.mumei_client import MumeiClient
from agent.pattern_library import PatternLibrary
from agent.strategies.fix_strategy import _build_prompt_for_report, response_token_count
from agent.strategies.retry_history import RetryAttempt, RetryHistory

if TYPE_CHECKING:
    from agent.metrics import Metrics

_logger = logging.getLogger(__name__)

_DIAGNOSE_SYSTEM = (
    "You are a formal verification expert specializing in the Mumei language. "
    "Analyze the verification failure and output a JSON diagnosis."
)

_DIAGNOSE_USER_TEMPLATE = """\
The following Mumei code failed formal verification.

# Source code:
{source_code}

# Error log:
{error_log}

# Verification report (structured):
{report_json}
{approach_switch_instruction}
Analyze the failure and respond with ONLY a JSON object (no markdown fences):
{{
  "root_cause": "<concise description of why verification failed>",
  "fix_approach": "<specific strategy to fix the code>",
  "target_section": "<one of: requires | ensures | body | effects>"
}}
"""

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

_APPROACH_SWITCH_INSTRUCTION = (
    "\n# IMPORTANT\n"
    "The previous approach failed to resolve this error. "
    "You MUST try a fundamentally different fix strategy.\n"
)

_MAX_INTERNAL_RETRIES = 2


def _extract_code(content: str) -> str:
    """Extract code from markdown fences or return raw content."""
    code_match = re.search(r'```\w*\s*\n(.*?)```', content, re.DOTALL)
    if code_match:
        return code_match.group(1).strip()
    return content.strip()


def _parse_diagnosis(content: str) -> dict:
    """Parse LLM diagnosis response into a dict.

    Handles both raw JSON and JSON inside markdown fences.
    """
    # Try to extract from code fences first
    fence_match = re.search(r'```(?:json)?\s*\n(.*?)```', content, re.DOTALL)
    text = fence_match.group(1).strip() if fence_match else content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "root_cause": "unknown",
            "fix_approach": "apply general fix",
            "target_section": "requires",
        }


def _diagnose(
    client: OpenAI,
    model: str,
    source_code: str,
    error_log: str,
    report_data: dict,
    *,
    approach_switch: bool = False,
) -> tuple[dict, int]:
    """Run Stage 1 diagnosis and return a parsed diagnosis dict.

    Args:
        client: OpenAI-compatible client.
        model: Model name.
        source_code: Current source code.
        error_log: Verification error output.
        report_data: Structured verification report.
        approach_switch: When True, inject an instruction telling the LLM
            to try a fundamentally different strategy.

    Returns:
        dict with keys ``root_cause``, ``fix_approach``, ``target_section``.
    """
    report_json = json.dumps(report_data, indent=2, ensure_ascii=False)
    switch_text = _APPROACH_SWITCH_INSTRUCTION if approach_switch else ""

    diagnose_prompt = _DIAGNOSE_USER_TEMPLATE.format(
        source_code=source_code,
        error_log=error_log,
        report_json=report_json,
        approach_switch_instruction=switch_text,
    )

    diag_response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _DIAGNOSE_SYSTEM},
            {"role": "user", "content": diagnose_prompt},
        ],
    )
    return (
        _parse_diagnosis(diag_response.choices[0].message.content or ""),
        response_token_count(diag_response),
    )


def _build_retry_context(retry_history: RetryHistory) -> str:
    """Build the retry context section for the fix prompt.

    Returns an empty string on the first attempt (no history).
    """
    history_text = retry_history.format_for_prompt()
    diff_text = retry_history.error_diff()

    if not history_text:
        return ""

    parts: list[str] = []
    parts.append("\n## Previous Fix Attempts")
    parts.append(history_text)
    if diff_text:
        parts.append("\n## Error Diff from Last Attempt")
        parts.append(diff_text)
    if retry_history.is_same_error_repeating():
        parts.append(
            "\n## Important\n"
            "The same error has persisted across multiple attempts. "
            "You MUST use a fundamentally different approach."
        )
    return "\n".join(parts)


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

        fix_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _FIX_SYSTEM},
                {"role": "user", "content": fix_prompt},
            ],
        )
        fix_tokens = response_token_count(fix_response)
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
            new_report = validation["report"] or report_data

            retry_history.add(
                RetryAttempt(
                    attempt_number=len(retry_history.attempts) + 1,
                    source_code=fixed_code,
                    error_log=new_error_log,
                    report_data=new_report,
                    diagnosis=diagnosis,
                    action_class=action_class,
                    tokens_used=total_tokens,
                )
            )

            # Update context for next iteration
            source_code = fixed_code
            error_log = new_error_log
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
