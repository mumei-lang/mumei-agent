"""Generate strategy: generate -> verify -> fix pipeline."""
from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path

from openai import OpenAI

from agent.mumei_client import MumeiClient
from agent.metrics import Metrics

_logger = logging.getLogger(__name__)


def _extract_code(content: str) -> str:
    """Extract code from markdown fences or return raw content."""
    code_match = re.search(r'```\w*\s*\n(.*?)```', content, re.DOTALL)
    if code_match:
        return code_match.group(1).strip()
    return content.strip()


def _has_effects(spec: dict) -> bool:
    """Check whether the spec describes an atom with effects."""
    effects = spec.get("effects", [])
    return bool(effects)


def _select_prompt_module(spec: dict):
    """Select the appropriate prompt module based on the spec."""
    if _has_effects(spec):
        from agent.prompts import generate_stdlib
        return generate_stdlib
    from agent.prompts import generate_atom
    return generate_atom


def generate_code(
    client: OpenAI,
    model: str,
    spec: dict,
    config_max_retries: int = 5,
    mumei_client: MumeiClient | None = None,
    metrics: Metrics | None = None,
) -> tuple[str, bool]:
    """Generate Mumei code from a specification, verify, and fix if needed.

    Pipeline:
        1. Use LLM to generate .mm code from spec
        2. Run ``mumei check`` (parse check) on generated code
        3. Run ``mumei verify --json`` on generated code
        4. If verification fails, use existing fix_strategy to attempt repair
        5. Re-verify up to config_max_retries times

    Args:
        client: OpenAI-compatible client.
        model: Model name.
        spec: Specification dict with name, params, effects, etc.
        config_max_retries: Maximum number of fix attempts.
        mumei_client: MumeiClient for running check/verify.
        metrics: Optional Metrics instance for tracking.

    Returns:
        A tuple of (code, verified) where *code* is the generated (and
        potentially fixed) .mm source and *verified* indicates whether
        the code passed ``mumei verify``.
    """
    if metrics is None:
        metrics = Metrics()

    prompt_module = _select_prompt_module(spec)
    spec_json = json.dumps(spec, indent=2, ensure_ascii=False)

    # Stage 1: Initial generation
    metrics.record_attempt("generation")
    prompt = prompt_module.build_prompt(spec_json, "", {})

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

    generated_code = _extract_code(response.choices[0].message.content or "")
    if not generated_code:
        _logger.warning("LLM returned empty generation result")
        return "", False

    if mumei_client is None:
        metrics.record_success("generation")
        return generated_code, True

    # Stage 2+3: Check, verify, and fix loop
    current_code = generated_code
    last_violation_type = "generation"
    for attempt in range(config_max_retries):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mm", delete=False, encoding="utf-8"
            ) as tmp:
                tmp_path = tmp.name
                tmp.write(current_code)

            # Parse check
            check_result = mumei_client.check(tmp_path)
            if not check_result["success"]:
                _logger.info(
                    "Parse check failed on attempt %d: %s",
                    attempt + 1,
                    check_result["stderr"],
                )
                last_violation_type = "parse_error"
                metrics.record_attempt("parse_error")
                error_log = check_result["stdout"] + check_result["stderr"]
                current_code = _attempt_fix(
                    client, model, spec_json, current_code, error_log, {},
                    prompt_module, metrics,
                )
                continue

            # Full verification
            verify_result = mumei_client.verify(tmp_path)
            if verify_result["success"]:
                metrics.record_success(last_violation_type)
                return current_code, True

            _logger.info(
                "Verification failed on attempt %d", attempt + 1,
            )
            error_log = verify_result["stdout"] + verify_result["stderr"]
            report = verify_result["report"] or {}
            violation_type = report.get("violation_type", report.get("failure_type", "unknown"))
            last_violation_type = violation_type
            metrics.record_attempt(violation_type)

            current_code = _attempt_fix(
                client, model, spec_json, current_code, error_log, report,
                prompt_module, metrics,
            )

        finally:
            try:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    # Final check after all retries
    verified = False
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mm", delete=False, encoding="utf-8"
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(current_code)
        verify_result = mumei_client.verify(tmp_path)
        if verify_result["success"]:
            metrics.record_success(last_violation_type)
            verified = True
    finally:
        try:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    return current_code, verified


def _attempt_fix(
    client: OpenAI,
    model: str,
    spec_json: str,
    current_code: str,
    error_log: str,
    report: dict,
    prompt_module,
    metrics: Metrics,
) -> str:
    """Attempt to fix generated code using the LLM."""
    # Include both the spec and the current (broken) code so the LLM
    # can see what it generated and what went wrong.
    combined_source = (
        f"# Original specification:\n{spec_json}\n\n"
        f"# Current generated code (needs fixing):\n{current_code}"
    )
    fix_prompt = prompt_module.build_prompt(combined_source, error_log, report)

    fix_response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful programming assistant specializing "
                    "in the Mumei language with its effect system and Z3 formal verification. "
                    "Fix the code to pass verification."
                ),
            },
            {"role": "user", "content": fix_prompt},
        ],
    )

    fixed_code = _extract_code(fix_response.choices[0].message.content or "")
    if not fixed_code:
        return current_code
    return fixed_code
