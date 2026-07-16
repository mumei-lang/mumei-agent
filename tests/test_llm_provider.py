"""Tests for the OpenAI-compatible LLM provider."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from agent.config import AgentConfig
from agent.llm_provider import OpenAILLMProvider


def test_openai_provider_passes_max_tokens_when_configured() -> None:
    """`LLM_MAX_TOKENS` is forwarded to the chat completion request."""
    config = AgentConfig()
    object.__setattr__(config, "llm_max_tokens", 1024)

    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="hello"))]

    client = MagicMock()
    client.chat.completions.create.return_value = response

    provider = OpenAILLMProvider(config=config, client=client)
    result = provider.complete([{"role": "user", "content": "hi"}], "test-model")

    assert result == "hello"
    client.chat.completions.create.assert_called_once_with(
        model="test-model",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=1024,
    )


def test_openai_provider_omits_max_tokens_when_unconfigured() -> None:
    """No `max_tokens` is sent when `LLM_MAX_TOKENS` is not set."""
    config = AgentConfig()
    object.__setattr__(config, "llm_max_tokens", None)

    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content="hello"))]

    client = MagicMock()
    client.chat.completions.create.return_value = response

    provider = OpenAILLMProvider(config=config, client=client)
    result = provider.complete([{"role": "user", "content": "hi"}], "test-model")

    assert result == "hello"
    client.chat.completions.create.assert_called_once_with(
        model="test-model",
        messages=[{"role": "user", "content": "hi"}],
    )
