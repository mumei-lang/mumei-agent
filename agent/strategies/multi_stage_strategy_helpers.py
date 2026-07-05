"""Helper utilities for the multi-stage fix strategy."""
from __future__ import annotations

import json
import re

from openai import OpenAI

from agent.strategies.fix_strategy import response_token_count
from agent.strategies.retry_history import RetryHistory

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

_APPROACH_SWITCH_INSTRUCTION = (
    "\n# IMPORTANT\n"
    "The previous approach failed to resolve this error. "
    "You MUST try a fundamentally different fix strategy.\n"
)


def _default_prompt_report_truncate_chars() -> int:
    try:
        from agent.config import AgentConfig

        return AgentConfig().prompt_report_truncate_chars
    except Exception:
        return 4000


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
        response_token_count(diag_response, model),
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
