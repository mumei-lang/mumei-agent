"""Multi-stage fix strategy: diagnose → fix → validate."""
import json
import re
import tempfile
from pathlib import Path

from openai import OpenAI

from agent.mumei_client import MumeiClient
from agent.strategies.fix_strategy import _build_prompt_for_report


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

Apply the fix approach above. Output only the fixed code in ```mumei ... ``` format.
"""

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


def get_fix_multi_stage(
    client: OpenAI,
    model: str,
    source_code: str,
    error_log: str,
    report_data: dict,
    mumei_client: MumeiClient,
    source_path: str,
) -> str:
    """Generate a fix using a multi-stage LLM pipeline.

    Stage 1 (Diagnose): Analyze the report and produce a structured diagnosis.
    Stage 2 (Fix): Generate fixed code using the diagnosis + prompt template.
    Stage 3 (Validate): Verify the fix with mumei; retry Stage 2 up to
        ``_MAX_INTERNAL_RETRIES`` times on failure.

    Returns the fixed source code (best effort).
    """
    # --- Stage 1: Diagnose ---
    report_json = json.dumps(report_data, indent=2, ensure_ascii=False)
    diagnose_prompt = _DIAGNOSE_USER_TEMPLATE.format(
        source_code=source_code,
        error_log=error_log,
        report_json=report_json,
    )

    diag_response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _DIAGNOSE_SYSTEM},
            {"role": "user", "content": diagnose_prompt},
        ],
    )
    diagnosis = _parse_diagnosis(diag_response.choices[0].message.content or "")

    root_cause = diagnosis.get("root_cause", "unknown")
    fix_approach = diagnosis.get("fix_approach", "apply general fix")
    target_section = diagnosis.get("target_section", "requires")

    # --- Stage 2 & 3: Fix + Validate loop ---
    base_prompt = _build_prompt_for_report(source_code, error_log, report_data)

    best_fix = ""
    for retry in range(_MAX_INTERNAL_RETRIES + 1):
        fix_prompt = _FIX_USER_TEMPLATE.format(
            base_prompt=base_prompt,
            root_cause=root_cause,
            fix_approach=fix_approach,
            target_section=target_section,
        )

        fix_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _FIX_SYSTEM},
                {"role": "user", "content": fix_prompt},
            ],
        )

        fixed_code = _extract_code(fix_response.choices[0].message.content or "")
        if not fixed_code:
            continue

        best_fix = fixed_code

        # --- Stage 3: Validate ---
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mm", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(fixed_code)
                tmp_path = tmp.name

            validation = mumei_client.verify(tmp_path)
            if validation["success"]:
                return fixed_code  # Verified successfully!

            # Update error context for next retry
            error_log = validation["stdout"] + validation["stderr"]
            report_data = validation["report"] or report_data
            base_prompt = _build_prompt_for_report(
                fixed_code, error_log, report_data
            )
        except Exception:
            pass  # Validation infrastructure failure; return best effort
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    return best_fix
