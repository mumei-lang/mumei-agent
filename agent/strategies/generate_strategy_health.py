"""Generation-config and health helpers for generate strategy."""
from __future__ import annotations

import logging

from openai import OpenAI

from agent.llm_provider import complete_text
from agent.strategies.generate_strategy_prompt import _extract_code

_logger = logging.getLogger(__name__)

def _load_generation_config(spec: dict) -> AgentConfig | None:
    """Return an AgentConfig for generation-scoped feature flags."""
    try:
        from agent.config import AgentConfig
    except ImportError:  # pragma: no cover - defensive
        return None

    config = spec.get("_agent_config")
    if isinstance(config, AgentConfig):
        if not hasattr(config, "enable_generation_health_check"):
            config.enable_generation_health_check = True
        if not hasattr(config, "enable_dense_properties"):
            config.enable_dense_properties = False
        return config
    try:
        return AgentConfig()
    except Exception:
        return None

def _health_check_generated_code(
    spec_json: str,
    generated_code: str,
    model: str,
    config: AgentConfig | None,
    past_code_examples: list[str],
    *,
    track_example: bool = True,
) -> bool:
    if config is None or not config.enable_generation_health_check:
        if track_example:
            past_code_examples.append(generated_code)
        return True

    from agent.generation_health_checker import GenerationHealthChecker

    checker = GenerationHealthChecker(config)
    for past_code in past_code_examples:
        checker.add_past_example(past_code)

    result = checker.check_generation_health(
        spec_json,
        generated_code,
        generation_metadata={"model": model},
    )
    if track_example:
        past_code_examples.append(generated_code)
    if result.is_healthy:
        return True

    _logger.warning(
        "Generation health check failed: warnings=%s errors=%s",
        result.warnings,
        result.errors,
    )
    return False

def _regenerate_for_health(
    client: OpenAI,
    model: str,
    prompt: str,
    system_content: str,
    health_warnings: str,
) -> str:
    retry_prompt = (
        f"{prompt}\n\n"
        "# Generation Health Retry\n"
        "The previous generation did not sufficiently reflect the current specification "
        "or was too similar to prior examples. Regenerate from the specification, "
        "using the skeleton and current requirements as the source of truth.\n"
        f"Health warnings: {health_warnings}"
    )
    content = complete_text(
        client,
        [
            {"role": "system", "content": system_content},
            {"role": "user", "content": retry_prompt},
        ],
        model,
    )
    return _extract_code(content)
