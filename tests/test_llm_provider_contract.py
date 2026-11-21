"""Provider-independent contract tests for the LLM dispatch layer.

Callers may hand either an OpenAI-compatible client or an ``LLMProvider``
(OpenAI-compatible or MCP sampling) to ``complete_response`` /
``complete_text`` / ``openai_client_adapter``.  These tests pin the shared
response surface — ``response.choices[0].message.content`` and token
accounting — so both provider styles produce the same keys downstream
callers consume, regardless of which backend answered.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from mcp import types as mcp_types

from agent.config import AgentConfig
from agent.llm_provider import (
    McpSamplingLLMProvider,
    OpenAILLMProvider,
    complete_response,
    complete_text,
    openai_client_adapter,
)
from agent.strategies.fix_strategy_helpers import response_token_count

MESSAGES = [{"role": "user", "content": "hi"}]
MODEL = "test-model"
TEXT = "same assistant text"


class _StubProvider:
    """Minimal LLMProvider recording calls."""

    def __init__(self, text: str = TEXT) -> None:
        self.text = text
        self.calls: list[tuple[list[dict], str]] = []

    def complete(self, messages, model: str) -> str:
        self.calls.append((list(messages), model))
        return self.text


def _openai_response(text: str = TEXT, total_tokens: int | None = None):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    response.usage = (
        MagicMock(total_tokens=total_tokens) if total_tokens is not None else None
    )
    return response


def _openai_client(response) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def _sampling_provider(text: str = TEXT) -> McpSamplingLLMProvider:
    async def create_message(messages, **kwargs):
        return mcp_types.CreateMessageResult(
            role="assistant",
            content=mcp_types.TextContent(type="text", text=text),
            model="client-model",
        )

    session = SimpleNamespace(
        create_message=create_message,
        _client_params={"capabilities": {"sampling": {}}},
    )
    return McpSamplingLLMProvider(SimpleNamespace(session=session))


def test_complete_response_same_content_surface_for_both_styles() -> None:
    """Provider and OpenAI client paths expose identical response keys."""
    provider_response = complete_response(_StubProvider(), MESSAGES, MODEL)
    client_response = complete_response(_openai_client(_openai_response()), MESSAGES, MODEL)

    assert (
        provider_response.choices[0].message.content
        == client_response.choices[0].message.content
        == TEXT
    )
    # Token accounting reads the same key on both styles.
    assert response_token_count(provider_response, MODEL) == response_token_count(
        client_response, MODEL
    )


def test_complete_text_identical_for_both_styles() -> None:
    """``complete_text`` returns the same string whichever backend answered."""
    assert complete_text(_StubProvider(), MESSAGES, MODEL) == complete_text(
        _openai_client(_openai_response()), MESSAGES, MODEL
    ) == TEXT


def test_openai_client_adapter_forwards_request_and_matches_surface() -> None:
    """The adapter preserves (model, messages) and the raw client's surface."""
    provider = _StubProvider()
    raw_response = _openai_response(total_tokens=42)
    raw_client = _openai_client(raw_response)

    adapted = openai_client_adapter(provider).chat.completions.create(
        model=MODEL, messages=MESSAGES
    )
    raw = raw_client.chat.completions.create(model=MODEL, messages=MESSAGES)

    assert provider.calls == [(MESSAGES, MODEL)]
    assert adapted.choices[0].message.content == raw.choices[0].message.content == TEXT


def test_token_accounting_parity_across_styles() -> None:
    """Usage-bearing and usage-less responses count identically on both paths."""
    provider_response = complete_response(_StubProvider(), MESSAGES, MODEL)
    client_response = complete_response(
        _openai_client(_openai_response(total_tokens=42)), MESSAGES, MODEL
    )
    # Provider responses carry no usage -> 0, matching a usage-less client.
    usage_less_client = complete_response(
        _openai_client(_openai_response()), MESSAGES, MODEL
    )
    assert response_token_count(provider_response, MODEL) == 0
    assert response_token_count(usage_less_client, MODEL) == 0
    assert response_token_count(client_response, MODEL) == 42


def test_sampling_and_openai_providers_are_interchangeable() -> None:
    """MCP sampling and OpenAI-compatible providers yield identical results.

    This is the provider-independent contract the roadmap calls out: a caller
    switching between ``USE_MCP_SAMPLING`` and the OpenAI-compatible path must
    observe the same return-value surface.
    """
    config = AgentConfig()
    object.__setattr__(config, "llm_max_tokens", None)
    openai_provider = OpenAILLMProvider(
        config=config, client=_openai_client(_openai_response())
    )

    for provider in (openai_provider, _sampling_provider()):
        response = complete_response(provider, MESSAGES, MODEL)
        assert response.choices[0].message.content == TEXT
        adapted = openai_client_adapter(provider).chat.completions.create(
            model=MODEL, messages=MESSAGES
        )
        assert adapted.choices[0].message.content == TEXT
