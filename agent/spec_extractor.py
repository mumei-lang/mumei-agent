"""Natural-language to forge task spec extraction."""
from __future__ import annotations

import json
import logging

from openai import OpenAI

from agent import telemetry
from agent.config import AgentConfig
from agent.metrics import Metrics
from agent.mumei_client import MumeiClient
from agent.prompts.spec_extraction import (
    SPEC_EXTRACTION_SYSTEM_PROMPT,
    build_extraction_prompt,
)
from agent.generate import _normalize_forge_task_spec
from agent.strategies.generate_strategy import generate_code
from agent.strategies.spec_refinement import run_refinement_loop
from agent.spec_extractor_helpers import (
    _ATOM_NAME_RE,
    _RETRY_FEEDBACK_RAW_LIMIT,
    _catalog_to_prompt_text,
    _complete_json_closers,
    _extract_json,
    _format_retry_feedback,
    _json_object_candidate,
    _json_repair_candidates,
    _keyword_validation_errors,
    _load_existing_catalog,
    _matches_requirement_trigger,
    _parse_json_candidate,
    _remove_trailing_commas,
    _scan_std_catalog_local,
    _single_quoted_json_to_double,
    _strip_inline_json_comment,
    _strip_json_comments,
    _validate_extracted_spec,
    validate_forge_task_spec,
)

logger = logging.getLogger(__name__)

def extract_spec(
    client: OpenAI,
    model: str,
    natural_language: str,
    *,
    domain_hint: str = "",
    mumei_client: MumeiClient | None = None,
    max_retries: int = 3,
    metrics: Metrics | None = None,
    detect_ambiguity: bool = False,
    config: AgentConfig | None = None,
) -> dict:
    """Extract a forge task spec from natural language.

    Pipeline:
        1. (Optional) Call mumei MCP server's list_std_catalog() to get existing catalog
        2. Build extraction prompt with natural_language + domain_hint + catalog
        3. Call LLM to generate spec JSON
        4. Validate the output against forge task spec schema
        5. If validation fails, retry with error feedback
        6. Return validated spec dict

    Returns:
        A forge task spec dict compatible with forge_tasks/*.json format.
    """
    if not natural_language.strip():
        raise ValueError("natural_language must be non-empty")

    if detect_ambiguity:
        from agent.ambiguity_detector import AmbiguityDetector

        detector = AmbiguityDetector(config or AgentConfig())
        ambiguity_result = detector.detect_ambiguity(natural_language)
        for warning in ambiguity_result.warnings:
            logger.warning(warning)
        if ambiguity_result.errors:
            raise ValueError("; ".join(ambiguity_result.errors))
        if ambiguity_result.has_ambiguity:
            logger.warning(
                "Ambiguity detected in specification: %d findings",
                len(ambiguity_result.findings),
            )

    existing_catalog = _load_existing_catalog(mumei_client)
    base_prompt = build_extraction_prompt(
        natural_language,
        domain_hint=domain_hint,
        existing_catalog=existing_catalog,
    )
    feedback = ""
    attempts = max(1, max_retries)
    last_errors: list[str] = []

    for attempt in range(1, attempts + 1):
        if metrics is not None:
            metrics.record_extraction_attempt()
        prompt = base_prompt
        if feedback:
            prompt += (
                "\n\n# Previous extraction failed\n"
                f"{feedback}\n"
                "Return a corrected forge task spec JSON object."
            )

        tracer = telemetry.get_tracer(__name__)
        with tracer.start_as_current_span("llm.spec_extraction") as span:
            span.set_attribute("gen_ai.system", "openai-compatible")
            span.set_attribute("gen_ai.request.model", model)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SPEC_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
        raw = response.choices[0].message.content or ""
        try:
            spec = _extract_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_errors = [f"invalid JSON: {exc}"]
            feedback = _format_retry_feedback(raw, last_errors)
            continue

        validation_errors = _validate_extracted_spec(spec)
        if not validation_errors:
            validation_errors = _keyword_validation_errors(spec, natural_language)
        if not validation_errors:
            if metrics is not None:
                metrics.record_extraction_success()
            return spec
        last_errors = validation_errors
        feedback = _format_retry_feedback(raw, validation_errors)

    raise ValueError(
        f"failed to extract valid forge task spec after {attempts} attempts: "
        + "; ".join(last_errors)
    )


def extract_and_generate(
    client: OpenAI,
    model: str,
    natural_language: str,
    *,
    domain_hint: str = "",
    mumei_client: MumeiClient | None = None,
    max_extraction_retries: int = 3,
    max_generation_retries: int = 5,
    max_refinements: int = 3,
) -> tuple[str, bool, dict]:
    """Full pipeline: natural language → spec → verified code.

    Combines extract_spec() with the existing generate_code() and
    run_refinement_loop() from spec_refinement.py.

    Returns:
        A tuple of (code, verified, final_spec).
    """
    metrics = Metrics()
    spec = extract_spec(
        client,
        model,
        natural_language,
        domain_hint=domain_hint,
        mumei_client=mumei_client,
        max_retries=max_extraction_retries,
        metrics=metrics,
    )
    return run_refinement_loop(
        client,
        model,
        _normalize_forge_task_spec(spec),
        generate_code,
        max_refinements=max_refinements,
        config_max_retries=max_generation_retries,
        mumei_client=mumei_client,
        metrics=metrics,
    )
