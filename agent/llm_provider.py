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
from agent import telemetry

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

logger = logging.getLogger(__name__)

Message = Mapping[str, Any]


def _span_total_tokens(response: Any) -> int:
    """Best-effort ``usage.total_tokens`` extraction for span annotation."""
    return telemetry._response_total_tokens(response)


def _annotate_response(span: Any, response: Any, model: str | None = None) -> None:
    total = _span_total_tokens(response)
    if total:
        span.set_attribute("gen_ai.usage.total_tokens", total)
    # Also feed the OTel counter so token/cost/TPM is observable on every LLM
    # call path, not just fix/heal (#297).
    telemetry.record_llm_tokens(total, model=model)


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
        tracer = telemetry.get_tracer(__name__)
        with tracer.start_as_current_span("llm.complete") as span:
            span.set_attribute("gen_ai.system", "openai-compatible")
            if model:
                span.set_attribute("gen_ai.request.model", model)
            base_url = getattr(self.config, "base_url", None) if self.config else None
            if base_url:
                span.set_attribute("server.address", base_url)
            response = self._ensure_client().chat.completions.create(
                model=model,
                messages=list(messages),
            )
            _annotate_response(span, response, model)
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
        tracer = telemetry.get_tracer(__name__)
        with tracer.start_as_current_span("mcp_sampling.complete") as span:
            span.set_attribute("gen_ai.system", "mcp-sampling")
            if model:
                span.set_attribute("gen_ai.request.model", model)
            try:
                return self._complete_via_sampling(messages, model)
            except Exception as exc:
                if self.fallback is None:
                    raise
                logger.warning(
                    "MCP sampling failed; falling back to OpenAI-compatible LLM: %s", exc
                )
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
                metadata=telemetry.inject_trace_context(
                    {"mumei_agent_llm_provider": "mcp_sampling"}
                ),
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

    def complete_with_tools(
        self,
        messages: Sequence[Message],
        model: str,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
    ) -> "SamplingToolCompletion":
        """Send a tool-enabled ``sampling/createMessage`` request.

        Per the MCP 2025-11-25 specification, tool-enabled sampling requires
        the client to declare the ``sampling.tools`` capability during
        initialization; a :class:`RuntimeError` is raised otherwise (callers
        can catch it and fall back to text-only sampling or the OpenAI path).

        ``tools`` accepts ``mcp.types.Tool`` instances or plain mappings with
        ``name`` / ``inputSchema`` (and optional ``description``) keys.  Tool
        definitions are scoped to this single request — they are not
        registered on the server or reused across calls.

        ``tool_choice`` maps to ``ToolChoice.mode`` (``"auto"``, ``"required"``
        or ``"none"``).
        """
        tracer = telemetry.get_tracer(__name__)
        with tracer.start_as_current_span("mcp_sampling.complete_with_tools") as span:
            span.set_attribute("gen_ai.system", "mcp-sampling-tools")
            if model:
                span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("gen_ai.request.tool_count", len(tools))
            if tool_choice:
                span.set_attribute("gen_ai.request.tool_choice", tool_choice)
            return self._complete_with_tools_impl(messages, model, tools, tool_choice=tool_choice)

    def _complete_with_tools_impl(
        self,
        messages: Sequence[Message],
        model: str,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
    ) -> "SamplingToolCompletion":
        from mcp import types as mcp_types

        if not _client_supports_basic_sampling(self.ctx):
            raise RuntimeError("connected MCP client did not declare sampling capability")
        if not _client_supports_sampling_tools(self.ctx):
            raise RuntimeError(
                "connected MCP client did not declare the sampling.tools capability"
            )

        request_tools = [_to_sampling_tool(tool) for tool in tools]
        choice = mcp_types.ToolChoice(mode=tool_choice) if tool_choice else None
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
                metadata=telemetry.inject_trace_context(
                    {"mumei_agent_llm_provider": "mcp_sampling_tools"}
                ),
                tools=request_tools,
                tool_choice=choice,
            )
            if inspect.isawaitable(result):
                return await result
            return result

        result = _run_async_from_sync(call_sampling)
        return _parse_tool_sampling_result(result)


@dataclass
class SamplingToolCall:
    """A single tool invocation requested by the sampling model."""

    name: str
    id: str
    input: Mapping[str, Any]


@dataclass
class SamplingToolCompletion:
    """Result of a tool-enabled sampling request."""

    text: str
    tool_calls: list[SamplingToolCall]
    stop_reason: str | None = None


def _to_sampling_tool(tool: Any) -> Any:
    from mcp import types as mcp_types

    if isinstance(tool, mcp_types.Tool):
        return tool
    if isinstance(tool, Mapping):
        return mcp_types.Tool.model_validate(dict(tool))
    raise TypeError(f"unsupported sampling tool definition: {type(tool)!r}")


def _parse_tool_sampling_result(result: Any) -> SamplingToolCompletion:
    """Extract text and tool-use blocks from a create_message result.

    Handles both ``CreateMessageResult`` (single content block) and
    ``CreateMessageResultWithTools`` (list of content blocks).
    """
    from mcp import types as mcp_types

    content = getattr(result, "content", None)
    blocks: Sequence[Any]
    if isinstance(content, Sequence) and not isinstance(content, (str, bytes, bytearray)):
        blocks = content
    else:
        blocks = [content]

    text_parts: list[str] = []
    tool_calls: list[SamplingToolCall] = []
    for block in blocks:
        if isinstance(block, mcp_types.ToolUseContent):
            tool_calls.append(
                SamplingToolCall(
                    name=block.name,
                    id=block.id,
                    input=block.input or {},
                )
            )
            continue
        text = getattr(block, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    if not text_parts and not tool_calls:
        raise RuntimeError("MCP sampling response did not contain text or tool-use content")
    return SamplingToolCompletion(
        text="\n".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=getattr(result, "stopReason", None),
    )


def complete_text(llm_or_client: Any, messages: Sequence[Message], model: str) -> str:
    """Complete with either an LLMProvider or a legacy OpenAI-compatible client."""
    tracer = telemetry.get_tracer(__name__)
    with tracer.start_as_current_span("llm.complete_text") as span:
        if model:
            span.set_attribute("gen_ai.request.model", model)
        return _extract_openai_text(complete_response(llm_or_client, messages, model))


def complete_response(
    llm_or_client: Any,
    messages: Sequence[Message],
    model: str,
) -> Any:
    """Return an OpenAI-like response from either provider style."""
    tracer = telemetry.get_tracer(__name__)
    with tracer.start_as_current_span("llm.complete_response") as span:
        if model:
            span.set_attribute("gen_ai.request.model", model)
        chat = getattr(llm_or_client, "chat", None)
        completions = getattr(chat, "completions", None)
        if callable(getattr(completions, "create", None)):
            span.set_attribute("gen_ai.dispatch_path", "openai_client")
            response = completions.create(model=model, messages=list(messages))
            _annotate_response(span, response, model)
            return response
        complete = getattr(llm_or_client, "complete", None)
        if callable(complete):
            span.set_attribute("gen_ai.dispatch_path", "llm_provider")
            return _CompletionResponse([_Choice(_Message(str(complete(messages, model))))])
        span.set_attribute("gen_ai.dispatch_path", "openai_client_fallback")
        response = completions.create(model=model, messages=list(messages))
        _annotate_response(span, response, model)
        return response


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


_SENTINEL = object()


def _client_supports_basic_sampling(ctx: Context) -> bool:
    """Check whether the connected MCP client declared sampling capability.

    Resolution order:
      (a) Public API – ``session.client_params`` property +
          ``session.check_client_capability()``.
      (b) Private attribute fallback – ``session._client_params`` (kept for
          older SDK versions that lack the public property).
      (c) Unknown – return ``True`` (optimistic; preserves backward-compat
          behaviour where an uninitialised session is assumed capable).
    """
    session = getattr(ctx, "session", None)
    if session is None:
        return True

    # (a) Public API ---------------------------------------------------------
    cp = getattr(session, "client_params", _SENTINEL)
    if cp is not _SENTINEL:
        if cp is None:
            # Session exists but no initialisation params yet – optimistic.
            return True
        check = getattr(session, "check_client_capability", None)
        if callable(check):
            try:
                from mcp import types as mcp_types

                return check(
                    mcp_types.ClientCapabilities(
                        sampling=mcp_types.SamplingCapability(),
                    )
                )
            except Exception:
                logger.debug(
                    "check_client_capability raised; "
                    "falling back to direct client_params inspection"
                )
        # client_params exists but check_client_capability does not – inspect
        # the value directly via _field_value.
        capabilities = _field_value(cp, "capabilities")
        if capabilities is None:
            return True
        return _field_value(capabilities, "sampling") is not None

    # (b) Private attribute fallback -----------------------------------------
    logger.debug(
        "public client_params property not found on session; "
        "falling back to private _client_params"
    )
    client_params = getattr(session, "_client_params", None)
    if client_params is None:
        return True
    capabilities = _field_value(client_params, "capabilities")
    if capabilities is None:
        return True
    return _field_value(capabilities, "sampling") is not None


def _client_supports_sampling_tools(ctx: Context) -> bool:
    """Check whether the connected MCP client declared ``sampling.tools``.

    Unlike :func:`_client_supports_basic_sampling`, unknown or missing
    capability information resolves to ``False``: the MCP 2025-11-25 spec
    requires an explicit ``sampling.tools`` capability before a server may
    send tool-enabled sampling requests, so there is no optimistic fallback.
    """
    session = getattr(ctx, "session", None)
    if session is None:
        return False

    cp = getattr(session, "client_params", _SENTINEL)
    if cp is not _SENTINEL:
        if cp is None:
            return False
        check = getattr(session, "check_client_capability", None)
        if callable(check):
            try:
                from mcp import types as mcp_types

                return check(
                    mcp_types.ClientCapabilities(
                        sampling=mcp_types.SamplingCapability(
                            tools=mcp_types.SamplingToolsCapability(),
                        ),
                    )
                )
            except Exception:
                logger.debug(
                    "check_client_capability raised; "
                    "falling back to direct client_params inspection"
                )
        capabilities = _field_value(cp, "capabilities")
        sampling = _field_value(capabilities, "sampling") if capabilities is not None else None
        return sampling is not None and _field_value(sampling, "tools") is not None

    client_params = getattr(session, "_client_params", None)
    if client_params is None:
        return False
    capabilities = _field_value(client_params, "capabilities")
    if capabilities is None:
        return False
    sampling = _field_value(capabilities, "sampling")
    return sampling is not None and _field_value(sampling, "tools") is not None


def _field_value(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


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
