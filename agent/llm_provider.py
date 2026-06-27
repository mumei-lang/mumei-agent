"""LLM provider abstractions for OpenAI-compatible and MCP sampling calls."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import inspect
import logging
import os
import queue
import threading
from typing import TYPE_CHECKING, Any, Protocol

from agent.config import AgentConfig

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

logger = logging.getLogger(__name__)

Message = Mapping[str, Any]


class LLMProvider(Protocol):
    """Minimal text completion interface used by agent loops."""

    def complete(self, messages: Sequence[Message], model: str) -> str:
        """Return assistant text for a chat-style message list."""


def _extract_openai_text(response: Any) -> str:
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError):
        return ""


class OpenAILLMProvider:
    """LLM provider backed by the existing OpenAI-compatible client."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            config = self.config or AgentConfig()
            self._client = config.create_client()
        return self._client

    def complete(self, messages: Sequence[Message], model: str) -> str:
        response = self._ensure_client().chat.completions.create(
            model=model,
            messages=list(messages),
        )
        return _extract_openai_text(response)


class McpSamplingLLMProvider:
    """LLM provider that delegates completion to the connected MCP client."""

    def __init__(
        self,
        ctx: Context,
        *,
        fallback: LLMProvider | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.ctx = ctx
        self.fallback = fallback
        self.max_tokens = max_tokens or int(os.getenv("MCP_SAMPLING_MAX_TOKENS", "4096"))

    def complete(self, messages: Sequence[Message], model: str) -> str:
        try:
            return self._complete_via_sampling(messages, model)
        except Exception as exc:
            if self.fallback is None:
                raise
            logger.warning("MCP sampling failed; falling back to OpenAI-compatible LLM: %s", exc)
            return self.fallback.complete(messages, model)

    def _complete_via_sampling(self, messages: Sequence[Message], model: str) -> str:
        from mcp import types as mcp_types

        if not _client_supports_basic_sampling(self.ctx):
            raise RuntimeError("connected MCP client did not declare sampling capability")

        sampling_messages, system_prompt = _to_sampling_messages(messages)

        async def call_sampling() -> Any:
            result = self.ctx.session.create_message(
                sampling_messages,
                max_tokens=self.max_tokens,
                system_prompt=system_prompt or None,
                model_preferences=mcp_types.ModelPreferences(
                    hints=[mcp_types.ModelHint(name=model)] if model else None,
                    intelligencePriority=0.8,
                ),
                metadata={"mumei_agent_llm_provider": "mcp_sampling"},
            )
            if inspect.isawaitable(result):
                return await result
            return result

        result = _run_async_from_sync(call_sampling)
        content = getattr(result, "content", None)
        if isinstance(content, mcp_types.TextContent):
            return content.text
        text = getattr(content, "text", None)
        if isinstance(text, str):
            return text
        raise RuntimeError("MCP sampling response did not contain text content")


def complete_text(llm_or_client: Any, messages: Sequence[Message], model: str) -> str:
    """Complete with either an LLMProvider or a legacy OpenAI-compatible client."""
    return _extract_openai_text(complete_response(llm_or_client, messages, model))


def complete_response(
    llm_or_client: Any,
    messages: Sequence[Message],
    model: str,
) -> Any:
    """Return an OpenAI-like response from either provider style."""
    chat = getattr(llm_or_client, "chat", None)
    completions = getattr(chat, "completions", None)
    if callable(getattr(completions, "create", None)):
        return completions.create(model=model, messages=list(messages))
    complete = getattr(llm_or_client, "complete", None)
    if callable(complete):
        return _CompletionResponse([_Choice(_Message(str(complete(messages, model))))])
    return completions.create(model=model, messages=list(messages))


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _CompletionResponse:
    choices: list[_Choice]
    usage: Any | None = None


class _ChatCompletionsAdapter:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def create(self, *, model: str, messages: Sequence[Message], **_: Any) -> _CompletionResponse:
        return _CompletionResponse([_Choice(_Message(self.provider.complete(messages, model)))])


class _ChatAdapter:
    def __init__(self, provider: LLMProvider) -> None:
        self.completions = _ChatCompletionsAdapter(provider)


class LLMProviderOpenAIClientAdapter:
    """Expose an LLMProvider through the OpenAI chat.completions surface."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.chat = _ChatAdapter(provider)


def openai_client_adapter(provider: LLMProvider) -> LLMProviderOpenAIClientAdapter:
    return LLMProviderOpenAIClientAdapter(provider)


def _to_sampling_messages(
    messages: Sequence[Message],
) -> tuple[list[Any], str]:
    from mcp import types as mcp_types

    sampling_messages: list[Any] = []
    system_parts: list[str] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = _message_content_to_text(message.get("content", ""))
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        sampling_role = "assistant" if role == "assistant" else "user"
        sampling_messages.append(
            mcp_types.SamplingMessage(
                role=sampling_role,
                content=mcp_types.TextContent(type="text", text=content),
            )
        )
    if not sampling_messages:
        sampling_messages.append(
            mcp_types.SamplingMessage(
                role="user",
                content=mcp_types.TextContent(type="text", text=""),
            )
        )
    return sampling_messages, "\n\n".join(system_parts)


def _client_supports_basic_sampling(ctx: Context) -> bool:
    session = getattr(ctx, "session", None)
    client_params = getattr(session, "_client_params", None)
    if client_params is None:
        return True
    capabilities = getattr(client_params, "capabilities", None)
    if capabilities is None:
        return True
    return getattr(capabilities, "sampling", None) is not None


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content)


def _run_async_from_sync(factory: Any) -> Any:
    try:
        import anyio

        return anyio.from_thread.run(factory)
    except RuntimeError:
        pass

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def runner() -> None:
        try:
            result_queue.put((True, asyncio.run(factory())))
        except Exception as exc:  # pragma: no cover - defensive
            result_queue.put((False, exc))

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    ok, value = result_queue.get()
    if ok:
        return value
    raise value
