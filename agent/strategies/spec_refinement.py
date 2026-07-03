"""Specification Refinement Loop (P6-C).

When code fixes alone are insufficient to pass verification, this module
refines the original specification — weakening postconditions, strengthening
preconditions, or adjusting effects — and feeds the updated spec back into
the generation pipeline.

Typical flow::

    1. ``generate_code()`` exhausts its fix retries → verified == False
    2. Caller invokes ``refine_spec()`` with the original spec and the
       last verification report.
    3. ``refine_spec()`` asks the LLM to propose spec modifications.
    4. The caller retries ``generate_code()`` with the refined spec.
    5. Repeat up to ``max_refinements`` times.
"""
from __future__ import annotations

import json
import logging
import re

from openai import OpenAI

from agent.config import AgentConfig
from agent.intent_tracker import IntentDriftResult, IntentTracker
from agent.metrics import Metrics

_logger = logging.getLogger(__name__)

from agent.strategies.spec_refinement_helpers import (
    _load_contract_manifest,
    check_contract_integrity,
)


def refine_spec(
    client: OpenAI,
    model: str,
    spec: dict,
    report: dict,
    error_log: str = "",
    enable_intent_tracking: bool = True,
    config: AgentConfig | None = None,
) -> tuple[dict, IntentDriftResult | None]:
    """Ask the LLM to refine a specification based on a verification failure.

    The LLM is given the original spec and the structured verification report
    and asked to return a modified spec JSON that is more likely to be
    satisfiable while preserving the original intent.

    Args:
        client: OpenAI-compatible client.
        model: Model name.
        spec: The original (or previously refined) specification dict.
        report: The verification report from the last failed attempt.
        error_log: Raw error output from the verifier.

    Returns:
        A tuple of ``(refined_spec, intent_drift_result)``.
        ``intent_drift_result`` is ``None`` when tracking is disabled or the
        LLM fails to produce a refined dict.
    """
    spec_json = json.dumps(spec, indent=2, ensure_ascii=False)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    prompt = (
        "The following Mumei specification failed formal verification.\n"
        "The generated code could not be fixed within the retry budget.\n\n"
        f"# Specification:\n```json\n{spec_json}\n```\n\n"
        f"# Last verification report:\n```json\n{report_json}\n```\n\n"
    )
    if error_log:
        prompt += f"# Raw error log:\n{error_log}\n\n"

    prompt += (
        "Propose a REFINED specification that:\n"
        "1. Preserves the original intent as much as possible.\n"
        "2. Weakens postconditions (ensures) if they are unsatisfiable.\n"
        "3. Strengthens preconditions (requires) if the domain needs narrowing.\n"
        "4. Adjusts effects if there is an effect mismatch.\n"
        "5. Keeps the same JSON structure as the original spec.\n\n"
        "Return ONLY the refined JSON spec (no explanation).\n"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a specification engineer for the Mumei "
                    "proof-driven language. Refine specifications to make "
                    "them satisfiable while preserving intent."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content or ""

    # Extract JSON from markdown fences if present
    json_match = re.search(r'```(?:json)?\s*\n(.*?)```', raw, re.DOTALL)
    json_str = json_match.group(1).strip() if json_match else raw.strip()

    try:
        refined = json.loads(json_str)
        if not isinstance(refined, dict):
            _logger.warning("LLM returned non-dict JSON; using original spec")
            return spec, None
        effective_config = config or AgentConfig()
        manifest = (
            _load_contract_manifest(effective_config.contract_manifest_path)
            if effective_config.enable_contract_isolation
            else None
        )
        is_valid, contract_error = check_contract_integrity(spec, refined, manifest)
        if not is_valid:
            _logger.error(contract_error)
            raise ValueError(contract_error)

        if not enable_intent_tracking:
            return refined, None

        tracker = IntentTracker(effective_config)
        intent_drift_result = tracker.track_intent_drift(spec, refined)
        if not intent_drift_result.intent_preserved:
            _logger.warning(
                "Intent drift detected during spec refinement: %s",
                intent_drift_result.warnings,
            )
        return refined, intent_drift_result
    except json.JSONDecodeError:
        _logger.warning("LLM returned invalid JSON for spec refinement; using original spec")
        return spec, None


def run_refinement_loop(
    client: OpenAI,
    model: str,
    spec: dict,
    generate_fn,
    max_refinements: int = 3,
    config_max_retries: int = 5,
    mumei_client=None,
    metrics: Metrics | None = None,
    enable_intent_tracking: bool | None = None,
    config: AgentConfig | None = None,
) -> tuple[str, bool, dict]:
    """Run a specification refinement loop around code generation.

    Repeatedly generates code from *spec*, and if generation fails after
    all fix retries, refines the spec and tries again.

    Args:
        client: OpenAI-compatible client.
        model: Model name.
        spec: The original specification dict.
        generate_fn: A callable with signature
            ``(client, model, spec, config_max_retries, mumei_client, metrics)``
            returning ``(code, verified)`` or ``(code, verified, report)``.
            When the third element is provided it is used as the
            verification report for spec refinement; otherwise an empty
            report is used.

            .. note::

                The standard ``generate_code()`` returns a 2-tuple, so
                ``refine_spec()`` will receive an empty report.  To get
                full refinement quality, wrap ``generate_code`` so it
                returns ``(code, verified, last_report)``.
        max_refinements: Maximum number of spec refinements to attempt.
        config_max_retries: Max fix retries per generation attempt.
        mumei_client: MumeiClient instance.
        metrics: Optional Metrics instance.

    Returns:
        A tuple of ``(code, verified, final_spec)`` where *final_spec* is
        the (possibly refined) specification that produced *code*.
    """
    if metrics is None:
        metrics = Metrics()
    effective_config = config or AgentConfig()
    if enable_intent_tracking is None:
        enable_intent_tracking = effective_config.enable_intent_tracking

    current_spec = spec
    last_code = ""

    for refinement in range(max_refinements + 1):
        if refinement > 0:
            _logger.info(
                "Spec refinement attempt %d/%d", refinement, max_refinements,
            )

        result = generate_fn(
            client,
            model,
            current_spec,
            config_max_retries=config_max_retries,
            mumei_client=mumei_client,
            metrics=metrics,
        )

        # generate_fn may return (code, verified) or (code, verified, report)
        if len(result) >= 3:
            code, verified, last_report = result[0], result[1], result[2]
        else:
            code, verified = result[0], result[1]
            last_report = {}

        if verified:
            return code, True, current_spec

        last_code = code

        # If we've exhausted refinements, return what we have
        if refinement >= max_refinements:
            break

        # Refine the spec using the last verification report
        refined, intent_drift = refine_spec(
            client,
            model,
            current_spec,
            last_report,
            enable_intent_tracking=enable_intent_tracking,
            config=effective_config,
        )

        if intent_drift and not intent_drift.intent_preserved:
            _logger.warning(
                "Spec refinement may have drifted from original intent: %s",
                intent_drift.warnings,
            )

        # Check if the spec actually changed
        if refined == current_spec:
            _logger.info("Spec refinement produced no changes; stopping loop")
            break

        _logger.info(
            "Spec refined: %s",
            json.dumps(refined, indent=2, ensure_ascii=False)[:200],
        )
        current_spec = refined

    return last_code, False, current_spec
